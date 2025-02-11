from pyspark.sql.functions import input_file_name, regexp_replace, col, size, lit
from pyspark.ml.feature import Tokenizer, CountVectorizer, StopWordsRemover, MinHashLSH
from pyspark.sql import SparkSession
from pyspark import SparkConf

conf = SparkConf() \
    .setAppName("DocumentSimilarity") \
    .set("spark.driver.memory", "2000M") \
    .set("spark.executor.memory", "6000M") \
    .set("spark.executor.instances", "4") \
    .set("spark.executor.cores", "4")

spark = SparkSession.builder.config(conf=conf).getOrCreate()

#Διαβάζω τα data απο το HDFS
original_files = spark.sparkContext.wholeTextFiles("hdfs://master:9000/user/user/data/*-original.txt")
paraphrase_files = spark.sparkContext.wholeTextFiles("hdfs://master:9000/user/user/data/*-paraphrase.txt")

# Μετατροπή RDD σε DataFrame
original_df = original_files.toDF(["filename", "content"])
paraphrase_df = paraphrase_files.toDF(["filename", "content"])

# Προσθηκη στηλης type στα 2 dfs
original_df = original_df.withColumn("type", lit("original"))
paraphrase_df = paraphrase_df.withColumn("type", lit("paraphrase"))

#Ενωση των δυο dfs
df = original_df.union(paraphrase_df)

#Χωρίστε τα κείμενα σε λέξεις
tokenizer = Tokenizer(inputCol="content", outputCol="words")
df_tokens = tokenizer.transform(df)

# Remove stop words
stop_words_remover = StopWordsRemover(inputCol="words", outputCol="filtered_words")
df_tokens_stop = stop_words_remover.transform(df_tokens)

#Μετρήστε τη συχνότητα των λέξεων
vectorizer = CountVectorizer(inputCol="words", outputCol="features")
v_model = vectorizer.fit(df_tokens_stop)
df_vectorized = v_model.transform(df_tokens_stop)

# Αφαίρεση μηδενικών εγγραφών
def remove_empty_filtered_words(df):
    return df.filter(~(size(col("filtered_words")) == 0))

df_vectorized_f = remove_empty_filtered_words(df_vectorized)

#Δημιουργία του MinHashLSH
mh = MinHashLSH(inputCol="features", outputCol="hashes", numHashTables=2)
mhmodel = mh.fit(df_vectorized_f)

#Ευρεση ομοιων ζευγών 
result_df = mhmodel.approxSimilarityJoin(df_vectorized_f, df_vectorized_f, threshold=0.8, distCol="JaccardDistance")

#Φιλτραρισμα εγγραφων
def filter_rows(df):
    condition = (
        (col("datasetA.type") == "original") &
        (col("datasetB.type") == "paraphrase")
    )
    return df.filter(condition)

result_df_f = filter_rows(result_df)

#Επιλέγουμε τα 10 ζευγάρια με τις μικρότερες αποστάσεις
result_limit = result_df_f.sort("JaccardDistance").limit(10)

# Εμφανίζουμε τα αποτελέσματα
result = result_limit.select(col("datasetA.filename").alias("Original"), col("datasetB.filename").alias("Paraphrase"), "JaccardDistance")

result.show(truncate=False)

#Γράφουμε το αποτέλεσμα σε csv αρχειο
result.write.format("csv").mode("append").option("header", "true").save("/home/user/sparkout/")

